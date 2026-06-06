# Events Management — World-Class Comparison

## Our Implementation
- Event lifecycle: DRAFT → PUBLISHED → COMPLETED with attendee/revenue tallies on completion
- Multi-tier ticket types with per-type capacity, price, and configurable sale windows
- Two-tier capacity enforcement: per-ticket-type quantity AND event-level max_capacity
- Human-readable ticket references (EVT-YYYYMMDD-XXXXXX) with collision retry
- Check-in by ticket ID or ticket_ref; idempotency guard on double check-in
- Sponsorship management: tiered sponsors with amount tracking
- Event dashboard: ticket breakdown, attendance rate %, revenue, sponsor totals in one query
- BPM action: `crm.events.purchase_ticket` for workflow-driven registrations
- Default currency: KES (East Africa-first design)

**Integration points:** BPM workflow engine, GL (revenue), CRM contacts

---

## Benchmark: Eventbrite

| Feature | Ours | Eventbrite |
|---|---|---|
| Multiple ticket types | ✓ | ✓ |
| Capacity enforcement (dual-level) | ✓ | ✓ |
| Sale window (start/end dates) | ✓ | ✓ |
| QR code check-in | ✗ | ✓ |
| Online/virtual events | ✗ | ✓ |
| Attendee self-service portal | ✗ | ✓ |
| Discount codes / promo codes | ✗ | ✓ |
| Payment processing | ✗ (amount stored, not collected) | ✓ |
| Waitlist | ✗ | ✓ |
| Email communications | ✗ | ✓ |
| Sponsorship tracking | ✓ | ✗ |
| ERP/BPM integration | ✓ | ✗ |
| Multi-currency | ✓ (field present) | ✓ |

## Benchmark: Odoo Events

| Feature | Ours | Odoo |
|---|---|---|
| Ticket types | ✓ | ✓ |
| Check-in | ✓ | ✓ |
| Sale window enforcement | ✓ | ✓ |
| Sponsorship management | ✓ | ✓ |
| Website integration | ✗ | ✓ |
| Badge printing | ✗ | ✓ |
| Communication templates | ✗ | ✓ |
| Revenue dashboard | ✓ | ✓ |
| BPM triggers | ✓ | limited |

---

## Differentiation

**Where we exceed:**
- Dual-level capacity enforcement (ticket-type + event-level) prevents overselling even when multiple ticket types exist
- Sponsorship revenue is tracked alongside ticket revenue in the same dashboard query
- Ticket purchase is a BPM action — registration flows can be embedded in broader onboarding or CRM workflows
- Transactional: ticket creation + attendance stub + sold_count increment all commit atomically

**Remaining gaps:**
- No payment gateway integration — `amount_paid_cents` is recorded but no actual charge is initiated
- No attendee-facing portal or self-service cancellation
- No QR/barcode generation for tickets
- No waitlist management
- No discount codes or early-bird pricing
