# talent — World-Class HCM Comparison
Score: 34/100

## Current Capabilities

- **Recruitment pipeline**: Full requisition → candidate → application → interview → offer → hire flow with correct state machines
- **Requisition management**: Approval workflow, headcount tracking, compensation band (integer cents), skills JSONB, recruiter/hiring manager assignment
- **Candidate master**: Source tracking (REFERRAL, LINKEDIN, AGENCY, etc.), skills JSONB, resume/portfolio URLs, soft link to foundation Party for internal transfers
- **Interview scheduling**: Panel interviews via PostgreSQL `UUID[]` array, type enum (PHONE/VIDEO/ONSITE/TECHNICAL/PANEL), scorecard JSONB, 1–5 rating, HIRE/NO_HIRE/MAYBE recommendation
- **Offer lifecycle**: Base + signing bonus (integer cents), equity JSONB (cliff/vest/shares), expiry date, decline reason, `expire_stale_offers` batch job
- **Performance review skeleton**: Cycle types (ANNUAL/MID_YEAR/PROBATION/360 declared in comment), goals\_achievement and competency\_scores as JSONB lists, rating label (EXCEEDS/MEETS/BELOW/PIP), DRAFT→SUBMITTED→CALIBRATED→FINAL state machine
- **Training catalogue + enrollment**: Course with delivery mode, CPD hours, per-seat cost; enrollment with score, certificate URL, ENROLLED→IN\_PROGRESS→COMPLETED/WITHDRAWN/FAILED
- **Tenant isolation**: `tenant_id` on every table, all composite indexes include tenant
- **Audit trail**: `AuditMixin` on all models, `created_at`/`updated_at` on every table
- **Pipeline summary**: `pipeline_summary()` aggregates application counts by stage per requisition

---

## Gaps

### [CRITICAL] OKR / Goal Management is JSONB-only, not a first-class entity

**Missing**: Goals are stored as a JSONB array inside `PerformanceReview`, making cross-period analysis, cascading, and progress tracking impossible without full table scans.

**Impl**: Add `tal_goal` table with `employee_id`, `parent_goal_id` (self-referential FK for company→dept→individual cascade), `title`, `description`, `key_results JSONB` `[{kr_text, target_value, current_value, unit}]`, `weight Numeric(4,1)`, `cycle_id FK`, `status` (DRAFT/ACTIVE/COMPLETED/CANCELLED), `progress_pct` computed column. Add `TalentService.update_goal_progress()` that recalculates parent aggregates up the tree. SAP SuccessFactors Goal Management, Workday Goals, Oracle Performance Management all model this as a first-class entity with cascade alignment.

**Found in**: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, Lattice, 15Five

---

### [CRITICAL] 360-Degree Appraisal has no data model

**Missing**: `review_cycle='360'` is declared in a comment but there is no peer/subordinate/self nomination table — the schema cannot distinguish who evaluated whom in a multi-rater review.

**Impl**: Add `tal_review_participant` table: `review_id FK`, `participant_employee_id`, `participant_role` (SELF/PEER/MANAGER/SUBORDINATE/SKIP_LEVEL), `status` (INVITED/SUBMITTED/DECLINED), `submitted_at`, `responses JSONB`. Gate `submit_review()` to require all participants to submit before `finalise_review()` is callable. Add `TalentService.invite_reviewers()` and `TalentService.submit_peer_feedback()`. In Kenya context this matters: 360 is increasingly required for PSC-aligned appraisals in regulated sectors.

**Found in**: SAP SuccessFactors, Workday, Oracle, ADP Workforce Now, BambooHR

---

### [CRITICAL] Performance Improvement Plan (PIP) is a label, not a workflow

**Missing**: `rating_label='PIP'` is a string value; there is no PIP entity with action items, check-in schedule, escalation, or resolution.

**Impl**: Add `tal_pip` table: `employee_id`, `manager_id`, `triggered_by_review_id FK nullable`, `start_date`, `end_date`, `improvement_areas JSONB [{area, target_behaviour, success_criterion}]`, `check_in_frequency` (WEEKLY/BIWEEKLY), `status` (ACTIVE/EXTENDED/PASSED/TERMINATED), `outcome_notes`. Add `tal_pip_checkin` for timestamped progress notes. PIP termination should write back to payroll/offboarding hooks. Workday and SuccessFactors both model PIPs as structured workflows with legal hold implications.

**Found in**: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, ADP Workforce Now

---

### [CRITICAL] Succession Planning is entirely absent

**Missing**: No model for identifying critical roles, mapping successors, or tracking bench strength — zero tables or service methods.

**Impl**: Add `tal_succession_plan` (role/position\_id, review\_cycle, bench\_strength\_score), `tal_successor` (plan\_id FK, employee\_id, readiness\_level: READY_NOW/1_2_YEARS/3_5_YEARS, development\_actions JSONB, flight\_risk BOOLEAN). Add `TalentService.update_succession_plan()`. In Kenyan context, succession plans are increasingly required by regulators (CBK, IRA) for licensed financial institutions. Oracle HCM Cloud Succession Planning and Workday Succession have direct API parity here.

**Found in**: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, ADP Workforce Now

---

### [CRITICAL] High-Potential (HiPo) Identification is absent

**Missing**: No 9-box grid, potential rating, or HiPo designation — only performance rating exists.

**Impl**: Add `potential_rating` column to `PerformanceReview` (Numeric 1–5 or enum LOW/MEDIUM/HIGH/EXCEPTIONAL) and a `tal_nine_box_placement` table: `employee_id`, `cycle_id`, `performance_axis` (1–3), `potential_axis` (1–3), `box_label` (computed or stored), `placed_by`, `development_track_id FK nullable`. Add `TalentService.place_nine_box()`. Workday Talent Reviews and SuccessFactors Succession use 9-box as the canonical HiPo gate.

**Found in**: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, Cornerstone OnDemand

---

### [HIGH] Career Pathing and Skills Gap Analysis are absent

**Missing**: No career path model; no mechanism to compare employee's current skills against a target role's required skills to produce a gap.

**Impl**: Add `tal_career_path` table: `from_position_id`, `to_position_id`, `move_type` (LATERAL/UPWARD/CROSS_FUNCTIONAL), `typical_tenure_months`, `required_competencies JSONB`. Add `TalentService.skills_gap_analysis(employee_id, target_position_id, session)` that diffs `Candidate.skills` (or employee profile skills) against the target position's `required_skills`. Return `{matched: [...], gap: [...], excess: [...]}`. In Kenya context, "local content" hiring pressure makes skills gap analysis commercially important for large employers.

**Found in**: SAP SuccessFactors, Workday, Oracle, Cornerstone, LinkedIn Talent Insights

---

### [HIGH] Employee NPS / Pulse Surveys are absent

**Missing**: No survey, eNPS, or pulse check model anywhere in the talent module.

**Impl**: Add `tal_survey` (title, survey_type: ENPS/PULSE/EXIT/ONBOARDING, period, anonymised BOOLEAN), `tal_survey_question` (survey\_id FK, question\_text, question\_type: SCALE/CHOICE/TEXT, scale\_min, scale\_max), `tal_survey_response` (survey\_id, employee\_id nullable if anonymised, responses JSONB, submitted\_at). Add `TalentService.compute_enps(survey_id, session)` using standard NPS formula: `%Promoters(9-10) - %Detractors(0-6)`. BambooHR and Workday Peakon (Workday-acquired) treat eNPS as a core talent signal.

**Found in**: BambooHR, Workday (Peakon), SAP SuccessFactors (Qualtrics integration), Culture Amp

---

### [HIGH] Competency Framework is JSONB, not a governed catalogue

**Missing**: `competency_scores` is an unvalidated JSONB list; there is no master competency catalogue, no weighting governance, and no distinction between core/functional/leadership competencies.

**Impl**: Add `tal_competency` table: `code`, `name`, `competency_type` (CORE/FUNCTIONAL/LEADERSHIP/TECHNICAL), `description`, `behavioural_indicators JSONB [{level, indicator_text}]`, `is_active`. Add `tal_competency_profile` linking positions to required competencies with weights. Validate `PerformanceReview.competency_scores` JSONB against the catalogue at service layer. SuccessFactors Competency Library and Workday Competency Framework both treat this as a governed master-data domain.

**Found in**: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud, Cornerstone

---

### [HIGH] Learning & Development: CPD hours tracking and certification expiry absent

**Missing**: `TrainingEnrollment` tracks completion but there is no running CPD hours balance, no certification expiry/renewal alert, and no mandatory training compliance view.

**Impl**: Add `cpd_hours_earned Numeric(5,1)` to `TrainingEnrollment` (may differ from `duration_hours` if partial credit). Add `tal_certification` table: `employee_id`, `certification_name`, `issuing_body`, `issued_date`, `expiry_date`, `renewal_required BOOLEAN`, `course_id FK nullable`. Add `TalentService.expiring_certifications(tenant_id, within_days, session)` for compliance dashboards. ICPAK CPD requirements (40 hours/year for Kenyan CPAs) and LSK mandatory CPD make this commercially critical in Kenya.

**Found in**: SAP SuccessFactors, Oracle HCM Cloud, Sage HR, Cornerstone LMS

---

### [HIGH] Onboarding workflow is absent

**Missing**: Accepted offer does not trigger an onboarding checklist; there is no onboarding task model, buddy assignment, or equipment request integration.

**Impl**: Add `tal_onboarding_plan` (employee\_id, template\_id FK nullable, target\_start\_date, buddy\_id, status), `tal_onboarding_task` (plan\_id FK, task\_type: DOCUMENT/IT\_ACCESS/TRAINING/MEETING, due\_date, assigned\_to, completed\_at). Hook `accept_offer()` to auto-create an onboarding plan from a default template. Workday Onboarding and BambooHR Onboarding both fire this automatically on hire conversion.

**Found in**: BambooHR, Workday HCM, SAP SuccessFactors, Sage HR

---

### [HIGH] Interview calibration and debrief workflow missing

**Missing**: Individual interviewer scorecards exist but there is no debrief meeting model, aggregate calibration step, or consensus hiring decision separate from a single interviewer's recommendation.

**Impl**: Add `tal_interview_debrief` table: `application_id FK`, `facilitated_by`, `scheduled_at`, `attendee_ids UUID[]`, `aggregate_scorecard JSONB`, `hiring_decision` (PROCEED_OFFER/HOLD/REJECT), `decision_rationale`, `decided_at`. Add `TalentService.record_debrief()`. Google-style structured hiring and Workday Recruiting both treat the debrief as a distinct, auditable event required before offer creation is permitted.

**Found in**: Workday Recruiting, Greenhouse (integrated with Workday), Lever, SAP SuccessFactors

---

### [MEDIUM] Review calibration step has no multi-reviewer support

**Missing**: `PerformanceReview` has a single `reviewer_id`; CALIBRATED status exists but there is no calibration committee model, no forced distribution curve, and no cross-employee comparison view.

**Impl**: Add `tal_calibration_session` (cycle, department\_id, facilitator\_id, status, distribution\_target JSONB `{PIP: 5, BELOW: 10, MEETS: 60, EXCEEDS: 20, OUTSTANDING: 5}`), `tal_calibration_entry` (session\_id FK, review\_id FK, proposed\_label, final\_label, notes). Add `TalentService.finalise_calibration()` that bulk-updates `PerformanceReview.rating_label` from calibration entries. Workday Performance and SuccessFactors Calibration both enforce distribution targets at this step.

**Found in**: SAP SuccessFactors, Workday HCM, Oracle HCM Cloud

---

### [MEDIUM] Recruitment analytics beyond pipeline_summary are absent

**Missing**: `pipeline_summary()` counts applications by stage but there are no time-to-fill, time-to-hire, offer acceptance rate, source-of-hire effectiveness, or cost-per-hire metrics.

**Impl**: Add `TalentService.recruitment_metrics(tenant_id, from_date, to_date, session)` returning `{avg_days_to_fill, avg_days_to_hire, offer_acceptance_rate, hires_by_source, cost_per_hire_cents}`. These require querying across `Requisition.filled_at - created_at`, `Offer.responded_at - sent_at`, and `Candidate.source`. Workday Recruiting Analytics and SuccessFactors Recruiting dashboards expose all five as standard KPIs.

**Found in**: SAP SuccessFactors, Workday HCM, ADP Workforce Now, Oracle HCM Cloud

---

### [MEDIUM] Internal mobility / referral programme not modelled

**Missing**: `Candidate.source='REFERRAL'` exists as a string tag but there is no referral programme entity tracking who made the referral, referral bonus eligibility, or internal job posting for existing employees.

**Impl**: Add `referrer_employee_id UUID nullable` to `Candidate`. Add `tal_internal_posting` (requisition\_id FK, posted\_at, visible\_to\_grade\_min, closes\_at) to support internal-first posting before external sourcing. Add `TalentService.mark_referral_hired()` to trigger referral bonus workflow in payroll. Kenyan employers with large hourly workforces rely heavily on referral programmes; this is a standard feature in ADP and SuccessFactors.

**Found in**: SAP SuccessFactors, ADP Workforce Now, BambooHR, Sage HR

---

### [MEDIUM] Training cost tracking and budget governance are absent

**Missing**: `TrainingCourse.cost_cents` exists but there is no training budget by department, actual spend tracking, or budget vs. actual report.

**Impl**: Add `tal_training_budget` (department\_id, fiscal\_year, approved\_amount\_cents, committed\_amount\_cents, actual\_amount\_cents). On `enroll_training()`, check `committed_amount_cents + course.cost_cents <= approved_amount_cents` and raise `TrainingBudgetExceededError` if over. Update committed on enroll, actual on completion. Workday Learning and Oracle Learning Cloud both enforce budget gates at enrollment time.

**Found in**: SAP SuccessFactors, Workday Learning, Oracle HCM Cloud, Cornerstone

---

### [MEDIUM] Exit interview and attrition analytics are absent

**Missing**: No offboarding/exit survey, voluntary vs. involuntary termination classification, or attrition rate calculation.

**Impl**: Add `tal_exit_interview` (employee\_id, termination\_type: VOLUNTARY/INVOLUNTARY/RETIREMENT/REDUNDANCY, exit\_date, primary\_reason ENUM, secondary\_reasons JSONB, survey\_responses JSONB, conducted\_by, conducted\_at). Add `TalentService.attrition_report(tenant_id, period, session)` returning voluntary/involuntary counts, regrettable attrition flag (based on last performance rating), and department breakdown. Sage HR and BambooHR both include exit interview workflows as standard; critical for Kenya's Labour Relations Act compliance on termination documentation.

**Found in**: BambooHR, Sage HR, SAP SuccessFactors, Workday HCM

---

### [MEDIUM] Job offer letter generation and e-signature integration absent

**Missing**: `Offer` has compensation and dates but no document generation, no e-signature workflow, and no signed document storage.

**Impl**: Add `offer_letter_template_id FK nullable` to `Offer`, and `signed_document_url`, `signed_at`, `signature_provider` (DOCUSIGN/ADOBE_SIGN/HELLOSIGN/MANUAL) columns. Add `TalentService.generate_offer_letter(offer_id, session)` that renders a Jinja2 template with offer terms and returns a PDF URL. Gate `accept_offer()` to require `signed_document_url IS NOT NULL` when tenant config `REQUIRE_SIGNED_OFFER=True`. Workday and SuccessFactors both integrate DocuSign natively; in Kenya, e-signatures are legally valid under the Kenya Information and Communications Act.

**Found in**: Workday Recruiting, SAP SuccessFactors, BambooHR, ADP Workforce Now

---

### [MEDIUM] Currency localisation hardcoded to USD default

**Missing**: `currency_code` defaults to `"USD"` across `Requisition`, `Candidate`, `Offer`, and `TrainingCourse` — wrong for a system targeting Kenya (KES) or any African market.

**Impl**: Change all `default="USD"` to `default=None` and resolve currency from tenant configuration at service layer via `TenantConfig.default_currency_code`. Add a `CurrencyConversion` utility for multi-currency offer comparisons (relevant when comparing expatriate vs. local packages). ADP Workforce Now Africa and Sage HR both resolve currency from tenant/country config, not hardcoded defaults.

**Found in**: SAP SuccessFactors, ADP Workforce Now, Sage HR, Oracle HCM Cloud

---

### [MEDIUM] Approval workflow for training enrollment absent

**Missing**: `enroll_training()` creates an enrollment directly with no manager approval gate, training committee sign-off, or L&D policy enforcement.

**Impl**: Add `requires_approval BOOLEAN` to `TrainingCourse`. When `True`, `enroll_training()` creates enrollment with `status='PENDING_APPROVAL'` and fires a notification to `employee.manager_id`. Add `TalentService.approve_training_enrollment()` and `reject_training_enrollment()`. Workday Learning and SuccessFactors LMS both enforce configurable approval chains per course category (e.g., external conferences always require VP approval).

**Found in**: SAP SuccessFactors, Workday Learning, Oracle HCM Cloud, Cornerstone

---

## Scoring Rationale

| Domain | Max | Score | Notes |
|---|---|---|---|
| Recruitment pipeline | 20 | 14 | Strong core; missing debrief, calibration, referral programme, offer letter e-sign |
| Performance management | 20 | 5 | Schema exists; 360 multi-rater, PIP workflow, calibration committee all absent |
| Goal / OKR management | 15 | 1 | JSONB blob only; no cascade, no progress tracking |
| Learning & Development | 15 | 7 | Course + enrollment solid; CPD hours balance, certification expiry, budget gate absent |
| Succession / HiPo | 15 | 0 | Zero implementation |
| Analytics & reporting | 10 | 4 | Pipeline summary only; no time-to-fill, attrition, NPS |
| Localisation (KES, compliance) | 5 | 3 | Tenant isolation good; currency defaults wrong, Labour Act exit docs absent |
| **Total** | **100** | **34** | |

The recruitment pipeline is the strongest domain (ATS-grade for an ERP). Everything post-hire — performance, succession, development, HiPo — is skeletal. Closing the CRITICAL gaps (OKR entity, 360 multi-rater, PIP workflow, succession, HiPo 9-box) would lift the score to ~65. Full parity with SuccessFactors/Workday is a further ~30 points covering analytics depth, AI-driven matching, and regulatory compliance automation.
