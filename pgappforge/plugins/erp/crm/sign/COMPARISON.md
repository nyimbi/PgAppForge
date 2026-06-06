# E-Sign Portal — World-Class Comparison

## Our Implementation
- Create signature requests with parallel or sequential signing order
- Per-signatory one-use access tokens (SHA-256 hashed at rest; raw token sent via email link)
- Token invalidated on signing or declining — prevents replay
- Sequential order: next signatory automatically notified only after current signs
- Decline propagates immediately to request-level DECLINED status
- Expiry check (batch job): scans IN_PROGRESS requests past `expires_at`, marks EXPIRED
- Full audit log: CREATED / SENT / SIGNED / DECLINED / COMPLETED / EXPIRED per action with IP + user_agent
- BPM actions: `crm.sign.create_request` (create + send in one step), `crm.sign.check_status`
- BPM instance linkage: `bpm_instance_id` on request enables workflow polling

**Integration points:** BPM workflow engine, DMS (document_id binding), domain event bus

---

## Benchmark: DocuSign

| Feature | Ours | DocuSign |
|---|---|---|
| Parallel signing | ✓ | ✓ |
| Sequential signing order | ✓ | ✓ |
| Decline with reason | ✓ | ✓ |
| Expiry / deadline | ✓ | ✓ |
| Audit trail | ✓ (DB) | ✓ (tamper-evident PDF) |
| Token security (hashed at rest) | ✓ | ✓ |
| Drawn/typed signature capture | ✓ (base64 image) | ✓ |
| Certificate of completion (PDF) | ✗ | ✓ |
| In-document field placement | ✗ | ✓ |
| SMS / phone verification | ✗ | ✓ |
| Bulk send | ✗ | ✓ |
| Legal compliance (eIDAS, ESIGN) | ✗ (not certified) | ✓ |
| ERP/BPM workflow integration | ✓ native | ✗ (API only) |

## Benchmark: Adobe Sign

| Feature | Ours | Adobe Sign |
|---|---|---|
| Sequential/parallel routing | ✓ | ✓ |
| Audit trail | ✓ | ✓ |
| Decline | ✓ | ✓ |
| Web form (no account required) | ✗ | ✓ |
| Government-grade identity verify | ✗ | ✓ |
| ERP integration | ✓ native | ✗ (connector) |

## Benchmark: Odoo Sign

| Feature | Ours | Odoo |
|---|---|---|
| Token-based signing links | ✓ | ✓ |
| Sequential routing | ✓ | ✓ |
| Audit log | ✓ | ✓ |
| PDF annotation / field placement | ✗ | ✓ |
| SMS OTP verification | ✗ | ✓ |
| BPM integration | ✓ (deeper) | limited |

---

## Differentiation

**Where we exceed:**
- Access token is SHA-256 hashed before storage; raw token is ephemeral on the `_raw_token` transient attribute — database breach does not expose signing URLs
- BPM `create_request` action creates and sends in one atomic step, with `bpm_instance_id` enabling native workflow polling without polling loops
- Full audit log is queryable within the same ERP database — no external audit API call required

**Remaining gaps:**
- No in-document field placement (signature boxes, date fields, initials) — signature is a flat base64 image appended to the record, not embedded in the PDF
- No certificate of completion document generation
- No identity verification beyond email-delivered token
- Legal standing (eIDAS, US ESIGN Act) not certified — suitable for internal approvals, not regulated transactions
