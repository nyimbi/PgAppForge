# Employee Wellness — World-Class Comparison

## Our Implementation

- `WellnessService` with explicit SQLAlchemy session injection; stateless instance methods
- Program enrollment with participant cap enforcement (`max_participants`)
- Duplicate enrollment guard: blocks second ACTIVE enrollment in same program
- Check-in model: `wellbeing_score` (1-10), optional `energy_level` (1-10), `stress_level` (1-10)
- Automatic flag derivation: `BURNOUT_RISK` (score ≤ 3 or energy ≤ 2), `HIGH_STRESS` (stress ≥ 8)
- Idempotent check-ins: same employee+date updates existing record rather than creating duplicate
- Anonymous check-in flag for psychological safety
- EAP referral categories: MENTAL_HEALTH, SUBSTANCE, FINANCIAL, FAMILY, LEGAL, GRIEF, OTHER
- `get_wellbeing_trend()`: avg scores, IMPROVING/STABLE/DECLINING trend via first-half vs second-half comparison
- `get_org_wellness_summary()`: avg wellbeing, high-risk count, active enrollments, EAP open count
- `generate_wellness_report()`: compiles org summary for a period string and emits `WellnessReportGeneratedEvent`
- BPM action registered: `hcm.wellness.record_checkin`
- Domain events: `WellnessProgramEnrolledEvent`, `WellnessCheckInEvent`, `EapReferralCreatedEvent`, `WellnessReportGeneratedEvent`

## Benchmark: Virgin Pulse / Wellable / Odoo (no direct equivalent)

| Feature | Virgin Pulse | Wellable |
|---|---|---|
| Wellness program catalogue and enrollment | ✓ | ✓ |
| Daily / weekly wellbeing check-ins | ✓ | ✓ |
| Burnout and stress risk flagging | ✓ | ✓ |
| EAP referral management | ✓ | ✓ |
| Activity / fitness tracker integration | ✓ | ✓ |
| Challenges and gamification / points | ✓ | ✓ |
| Incentive and reward redemption | ✓ | ✓ |
| Biometric screening integration | ✓ | ✗ |
| Mental health content library | ✓ | ✓ |
| Manager wellness dashboard | ✓ | ✓ |
| Anonymous reporting and aggregation | ✓ | ✓ |
| HIPAA / GDPR compliant data handling | ✓ | ✓ |
| Multi-tenant isolation | ✗ | SaaS only |
| BPM workflow trigger actions | ✗ | ✗ |
| ERP-native (no separate SaaS vendor) | ✗ | ✗ |

## Differentiation

**Gaps vs market leaders:**
- No fitness tracker or wearable integration (steps, sleep, HRV)
- No gamification, challenges, or points/rewards system
- No content library (articles, videos, meditation sessions)
- Trend analysis is simple first-half/second-half split — no time-series regression
- HIPAA/GDPR data classification and consent management not implemented
- No biometric screening or health risk assessment questionnaires

**Strengths:**
- ERP-native: no third-party SaaS vendor, no SSO integration complexity, no data egress
- Automatic burnout/stress flag derivation at check-in time enables proactive EAP routing from BPM workflows
- Idempotent check-ins prevent duplicate records from mobile app retries
- Anonymous flag allows honest reporting without identity exposure
- Participant cap prevents over-enrollment without a waitlist queue
- Multi-tenant by design; Virgin Pulse and Wellable are single-tenant SaaS
- `generate_wellness_report()` produces a structured dict suitable for PDF/Excel export pipelines
