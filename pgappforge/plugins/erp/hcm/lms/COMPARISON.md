# Learning Management System — World-Class Comparison

## Our Implementation

- **Course lifecycle**: DRAFT → PUBLISHED state machine; max_attempts enforcement per employee; due-date computation from `course.due_days`
- **Per-lesson progress tracking**: enrollment creates one `LmsProgress` row per lesson; SCORM data dict merged on each `complete_lesson` call; time-spent accumulation
- **Automatic course completion**: `_try_complete_course` fires after every lesson completion; evaluates all required lessons, computes average score, sets COMPLETED/FAILED, auto-issues certificate if passed
- **Mandatory compliance engine**: `check_mandatory_compliance` scans all PUBLISHED mandatory courses, identifies overdue enrollments, emits `MandatoryTrainingOverdueEvent` per violation
- **Course analytics**: enrollment count, completion rate %, pass rate %, average score, average duration hours — all in a single query pass
- **BPM integration**: `hcm.lms.enroll` and `hcm.lms.check_compliance` registered as BPM actions

Kenya/Africa-specific features:
- Mandatory compliance tracking is critical for regulated sectors (banking CBK CPD, insurance IRA CPD, healthcare) common in Kenya
- `MandatoryTrainingOverdueEvent` feeds HR escalation workflows relevant to NGO/donor compliance reporting
- Multi-tenant isolation supports Sacco networks and county government deployments with shared course libraries

Integration points:
- **BPM**: enrollment and compliance check callable from process definitions (e.g., onboarding process triggers mandatory course enrollment)
- **HR Analytics**: course completion data feeds workforce development metrics in the analytics module
- **Event bus**: `CoursePublishedEvent`, `EnrollmentCreatedEvent`, `LessonCompletedEvent`, `CourseCompletedEvent`, `CertificateIssuedEvent`, `MandatoryTrainingOverdueEvent`

---

## Benchmark: Workday / SAP SuccessFactors

| Feature | Status |
|---|---|
| Course publish lifecycle with state guard | ✓ |
| Per-lesson progress with SCORM data | ✓ |
| Automatic certificate issuance on pass | ✓ |
| Mandatory compliance tracking + alerting | ✓ |
| Course analytics (completion, pass rate, avg duration) | ✓ |
| SCORM 1.2 / SCORM 2004 / xAPI (Tin Can) full runtime | ✗ (data dict only; no LRS) |
| Learning path / curriculum sequencing | ✗ |
| ILT (instructor-led training) scheduling | ✗ |
| Skills framework integration | ✗ |
| External content provider connectors (LinkedIn Learning, Coursera) | ✗ |
| Blended learning (online + classroom mix) | ✗ |
| Social learning / discussion forums | ✗ |
| Mobile offline learning | ✗ |
| AI-driven course recommendations | ✗ |

---

## Benchmark: Darwinbox (African market leader)

Darwinbox Learning is a relatively thin module; its strength is integration with the broader HCM and mobile access.

| Feature | Status |
|---|---|
| Course catalogue with enrollment | ✓ (we match) |
| Compliance / mandatory training alerts | ✓ (we match and exceed with BPM integration) |
| Certificate issuance | ✓ (we match) |
| Mobile-first course consumption | ✗ |
| Manager visibility into team completion | ✗ (no dedicated manager dashboard in LMS) |
| Pre-built compliance content libraries | ✗ |
| Integration with performance module (goals linked to learning) | ✗ |

---

## Differentiation

Where we exceed the benchmark:
- BPM-native enrollment: Darwinbox and most mid-market LMS treat enrollment as a standalone action; our `hcm.lms.enroll` BPM action makes it a first-class step in any business process (onboarding, promotion, role change)
- `check_mandatory_compliance` with event emission is more operational than Darwinbox's report-based compliance view — it can trigger immediate escalation workflows
- Auto-certificate issuance with `certificate_ref` is built in, not an add-on

Remaining gaps:
- No Learning Record Store (LRS) — SCORM runtime is a stub dict, not a standards-compliant runtime
- No learning path / curriculum concept
- No ILT module (instructor scheduling, room booking, attendance)
- No skills taxonomy link
- No manager-facing LMS dashboard (team completion rates, overdue reports)
- No content authoring integration (SCORM package upload)
