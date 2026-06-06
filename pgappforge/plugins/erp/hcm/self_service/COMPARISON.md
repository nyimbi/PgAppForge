# Employee Self-Service — World-Class Comparison

## Our Implementation

- `SelfServiceService` covering leave, profile updates, announcements, and dashboards
- Leave types: ANNUAL, SICK, MATERNITY, PATERNITY, COMPASSIONATE, STUDY, UNPAID
- Business-day counting (Mon–Fri) via `_count_business_days()`
- Balance auto-provisioned on first access using `_DEFAULT_ENTITLEMENTS` per leave type (ANNUAL 21d, SICK 10d, MATERNITY 90d, PATERNITY 14d)
- Balance deducted on approval; restored on cancellation of approved leave
- Leave state machine: PENDING → APPROVED / REJECTED / CANCELLED
- Profile update request workflow: PENDING → APPROVED / REJECTED with reviewer audit trail (`reviewed_by`, `reviewed_at`)
- `get_employee_dashboard()`: leave balances, last 3 payslips (`EssDocument`), pending/approved requests, active announcements
- `get_manager_dashboard()`: pending leave for direct reports, team on leave today, announcements
- Announcement model: URGENT/HIGH/NORMAL/LOW priority, expiry, audience roles, pin flag; priority via SQL CASE expression
- BPM action registered: `hcm.self_service.approve_leave`
- Domain events: `LeaveRequestSubmittedEvent`, `LeaveRequestApprovedEvent`, `LeaveRequestRejectedEvent`, `ProfileUpdateRequestedEvent`, `AnnouncementPublishedEvent`
- Default entitlements match Kenya Employment Act 2007 minimums

## Benchmark: Workday Employee Self-Service / Darwinbox ESS

| Feature | Workday ESS | Darwinbox ESS |
|---|---|---|
| Leave request and approval workflow | ✓ | ✓ |
| Leave balance tracking with carryover | ✓ | ✓ |
| Public holiday calendar integration | ✓ | ✓ |
| Profile update requests with approval | ✓ | ✓ |
| Payslip and tax document access | ✓ | ✓ |
| Employee and manager dashboards | ✓ | ✓ |
| Org chart and directory | ✓ | ✓ |
| Benefits enrollment and changes | ✓ | ✓ |
| Leave accrual (pro-rata monthly) | ✓ | ✓ |
| Half-day leave requests | ✓ | ✓ |
| Carry-over rules and expiry | ✓ | ✓ |
| Mobile app | ✓ | ✓ |
| WhatsApp / USSD interface | ✗ | ✓ |
| Multi-tenant isolation | ✗ | SaaS only |
| BPM-native approval routing | ✓ (limited) | ✗ |

## Differentiation

**Gaps vs market leaders:**
- Business-day counter ignores public holidays — critical for Kenya (Jamhuri Day, Madaraka Day, etc.)
- No leave accrual engine; entitlements are annual lump-sum only
- `carried_over_days` field exists but carry-over logic is not implemented
- No half-day leave support
- Profile update approval does not apply changes to the employee record — that step is outside the service layer
- No mobile app or WhatsApp/USSD interface — significant gap for field-based workers
- No expense claims, benefits enrollment, or org-chart self-service

**Strengths:**
- `hcm.self_service.approve_leave` BPM action enables arbitrarily complex multi-level approval routing; Darwinbox uses a fixed approval matrix
- Balance restoration on cancellation of approved leave is correctly atomic; many systems require manual HR correction
- Announcement priority ordering via SQL CASE avoids application-level sort on large datasets
- `ProfileUpdateRequest` enforces four-eyes principle on sensitive field changes (bank details, address) before any mutation
- Multi-tenant by design with per-entity leave policy support; both Workday and Darwinbox are single-tenant SaaS
- Default entitlements aligned to Kenya Employment Act 2007 and 2021 Amendment out of the box
