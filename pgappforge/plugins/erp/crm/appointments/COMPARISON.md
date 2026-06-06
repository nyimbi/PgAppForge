# Appointments & Booking — World-Class Comparison

## Our Implementation
- Available slot computation: loads staff availability windows (by `day_of_week`) then subtracts booked appointments (with configurable buffer) and `StaffBlockedSlot` records
- Advance booking gates: `min_advance_hours` and `max_advance_days` enforced on both slot listing and booking
- Double-booking prevention: slot re-validated at `book_appointment()` time (race-safe within a transaction)
- Buffer time between appointments: configurable `buffer_minutes` per service
- Eligible staff list per service; per-service pricing and currency
- Booking reference generation (APT-XXXXX) with uniqueness retry
- Automated reminders: batch `send_reminders(hours_before)` marks `reminder_sent=True` atomically
- Staff schedule view: date-range query over non-cancelled appointments
- BPM action: `crm.appointments.book` for workflow-driven booking

**Integration points:** BPM workflow engine, CRM contacts, GL (amount_cents per appointment)

---

## Benchmark: Calendly

| Feature | Ours | Calendly |
|---|---|---|
| Availability windows by day of week | ✓ | ✓ |
| Buffer time between bookings | ✓ | ✓ |
| Min/max advance booking | ✓ | ✓ |
| Blocked slots | ✓ | ✓ |
| Round-robin staff assignment | ✗ | ✓ |
| Calendar sync (Google/Outlook) | ✗ | ✓ |
| Group/collective scheduling | ✗ | ✓ |
| Embedded booking widget | ✗ | ✓ |
| Payment at booking (Stripe) | ✗ | ✓ |
| Automated reminders | ✓ (batch) | ✓ (email/SMS) |
| Cancellation / rescheduling portal | ✗ | ✓ |
| ERP/BPM integration | ✓ native | ✗ (webhook only) |
| Multi-service / multi-staff | ✓ | ✓ |

## Benchmark: Odoo Appointments

| Feature | Ours | Odoo |
|---|---|---|
| Staff availability rules | ✓ | ✓ |
| Buffer time | ✓ | ✓ |
| Online booking page | ✗ | ✓ |
| Calendar integration | ✗ | ✓ |
| SMS/Email reminders | ✓ (batch infra) | ✓ |
| Recurring appointments | ✗ | ✓ |
| BPM integration | ✓ (deeper) | limited |

---

## Differentiation

**Where we exceed:**
- Slot computation reads both `StaffAvailability` (recurring windows) and `StaffBlockedSlot` (ad-hoc blocks) in a single query pass — no stale cache issues
- Race-condition safe: slot is re-validated inside `book_appointment()` within the same transaction; two simultaneous bookings for the same slot cannot both succeed
- BPM integration enables appointments as workflow steps (e.g., auto-book a follow-up consultation after a lead reaches a score threshold)

**Remaining gaps:**
- No external calendar sync (Google Calendar, Outlook) — availability is managed entirely within the ERP
- No customer-facing booking portal or embeddable widget
- No round-robin or load-balanced staff assignment
- No payment collection at booking time
- No recurring appointment support
- Reminder dispatch is a placeholder (`_dispatch_reminder`); actual email/SMS requires wiring to a notification provider
