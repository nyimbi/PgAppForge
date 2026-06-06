# WhatsApp Business Integration — World-Class Comparison

## Our Implementation

- Stateless `WhatsAppService` with outbox pattern: HTTP delivery worker is deliberately decoupled
- Template message: validates APPROVED status before queuing; raises `WhatsAppTemplateNotFoundError` on missing/unapproved template
- Text message: queued as OUTBOUND/QUEUED; 24-hour service window policy documented but enforced by delivery worker
- Inbound processing: find-or-create `WhatsAppConversation` per phone+tenant; increments `message_count`, sets `last_message_at`
- Delivery status update by `wa_message_id` with SENT/DELIVERED/READ/FAILED transitions and timestamping
- Webhook handler: HMAC-SHA256 signature verification (`X-Hub-Signature-256`) before any processing
- Webhook routing: `messages.statuses` → `update_delivery_status`; `messages.inbound` → `process_inbound`
- Dual payload format support: WhatsApp Cloud API nested format and flat BSP format
- Analytics: delivery rate %, read rate %, active conversations, inbound count — all computed via SQL COUNT
- `get_pending_outbound()` FIFO queue for delivery worker polling
- `get_conversation_history()` ordered by `sent_at DESC NULLS LAST`
- BPM actions registered: `platform.whatsapp.send_template`, `platform.whatsapp.send_text`
- `WhatsAppWebhookLog` row persisted for every webhook; error stored on failure for retry
- Domain events: `WhatsAppMessageSentEvent`, `WhatsAppMessageDeliveredEvent`, `WhatsAppMessageReadEvent`, `WhatsAppInboundMessageEvent`, `WhatsAppConversationStartedEvent`

## Benchmark: WhatsApp Business API Direct / Twilio Conversations

| Feature | WA Cloud API (direct) | Twilio Conversations |
|---|---|---|
| Template message sending | ✓ | ✓ |
| Free-form text (within 24h window) | ✓ | ✓ |
| Inbound message receiving via webhook | ✓ | ✓ |
| Delivery / read receipts | ✓ | ✓ |
| HMAC webhook signature verification | ✓ | ✓ |
| Media messages (image, video, document) | ✓ | ✓ |
| Interactive messages (buttons, lists) | ✓ | ✓ |
| Conversation threading and history | ✓ | ✓ |
| Multi-agent inbox / assignment | ✗ | ✓ |
| Chatbot / flow builder integration | ✗ | ✓ |
| Opt-in / opt-out management | ✓ | ✓ |
| Phone number management / WABA setup | ✓ | ✓ (abstracted) |
| Multi-tenant message isolation | N/A | ✗ (single account) |
| Outbox pattern (decouple HTTP from domain) | ✗ | ✗ |
| ERP BPM workflow trigger actions | ✗ | ✗ |

## Differentiation

**Gaps vs market leaders:**
- No media message support (IMAGE, VIDEO, DOCUMENT sending — only body/caption received)
- No interactive message types (buttons, quick replies, list pickers)
- No opt-in/opt-out consent management or GDPR suppression list
- Multi-agent inbox and ticket assignment absent
- Template management UI / sync from WhatsApp Business Manager not implemented

**Strengths:**
- Outbox pattern fully decouples HTTP latency from domain writes — transaction safety without blocking
- HMAC verification with `hmac.compare_digest` prevents timing attacks at service layer, not just controller
- Dual-format webhook parser handles both Cloud API and third-party BSP payloads transparently
- BPM action registration enables no-code workflow nodes to send WhatsApp messages
- `WhatsAppWebhookLog` provides a durable retry queue; failed events are not silently dropped
- Multi-tenant isolation at every query — a single deployment serves multiple WABA accounts
- Analytics computed in SQL, not application memory — scales to millions of messages
