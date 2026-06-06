# Employee Referrals — World-Class Comparison

## Our Implementation

- `ReferralService` with explicit SQLAlchemy session injection; stateless instance methods
- Typed state machine with explicit transition table: SUBMITTED → SCREENING → INTERVIEWING → OFFERED → HIRED (terminal); REJECTED/WITHDRAWN/EXPIRED from any non-terminal state
- Position eligibility check against `program.eligible_positions` list at submission time
- Reward evaluation on HIRED transition: `after_days` condition (submission age gate) enforced before reward creation
- Reward lifecycle: PENDING → APPROVED → PAID with `payment_ref` and `paid_at` timestamps
- Reward types: CASH (and others via `program.reward_type`)
- `get_referrer_stats()`: submissions, hired count, conversion rate, rewards paid/pending cents
- `get_program_analytics()`: by-status breakdown, conversion rate, total committed reward cents
- BPM action registered: `hcm.referral.update_status`
- Domain events: `ReferralSubmittedEvent`, `ReferralHiredEvent`, `ReferralRewardPaidEvent`, `ReferralExpiredEvent`
- `reward_eligible` flag set on submission record when reward created

## Benchmark: Greenhouse Referrals / Odoo Referrals

| Feature | Greenhouse Referrals | Odoo Referrals |
|---|---|---|
| Employee referral submission portal | ✓ | ✓ |
| Candidate pipeline status tracking | ✓ | ✓ |
| Configurable reward amounts and types | ✓ | ✓ |
| Reward approval and payout workflow | ✓ | ✓ |
| Position-level eligibility rules | ✓ | ✓ |
| Social sharing / referral link generation | ✓ | ✓ |
| Leaderboard / gamification | ✓ | ✓ |
| Duplicate candidate detection | ✓ | ✗ |
| ATS integration (sync candidate status) | ✓ | ✓ |
| Probation pass condition for reward | ✓ | ✓ |
| Multi-program support | ✓ | ✓ |
| Automated reward payment via payroll | ✓ | ✓ |
| Multi-tenant isolation | ✗ | ✗ |
| Typed state machine with explicit transitions | ✗ | ✗ |

## Differentiation

**Gaps vs market leaders:**
- No social sharing or referral link generation
- No leaderboard or gamification layer
- `must_pass_probation` reward condition is a placeholder — requires external confirmation signal
- Duplicate candidate detection (same email across referrers) not enforced
- No payroll integration for reward disbursement; PAID status requires manual `payment_ref`
- No ATS sync — candidate status updates must be driven externally

**Strengths:**
- Explicit `_VALID_TRANSITIONS` dict makes illegal state transitions a hard error with a clear message — no silent no-ops
- `after_days` eligibility gate prevents premature reward creation for short-tenure hires
- Reward is decoupled from submission: a `ReferralReward` row is only created when conditions are met, not speculatively
- `get_referrer_stats()` and `get_program_analytics()` provide ROI visibility without a BI tool
- Multi-tenant by design; both Greenhouse and Odoo are single-tenant per installation
- BPM action enables ATS webhook → workflow → referral status update without custom code
