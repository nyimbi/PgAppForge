# Discuss (Team Chat) — World-Class Comparison

## Our Implementation
- Channels: PUBLIC, PRIVATE, DIRECT, SYSTEM types with owner/member roles
- Threaded replies (single-level); `reply_count` tracked atomically on parent
- Emoji reactions with deduplication stored as JSONB `{emoji: [user_ids]}`
- Per-member read pointer (`last_read_message_id`) with unread count query
- System notification channel: BPM engine fans workflow events into typed channels linked to `(module, record_id)`
- Cursor-based pagination for history (`before_id`)
- BPM actions: `platform.discuss.post_notification`, `platform.discuss.create_channel`

**Integration points:** BPM workflow engine, all ERP modules (system notifications), domain event bus

---

## Benchmark: Odoo Discuss

| Feature | Ours | Odoo |
|---|---|---|
| Public/Private/Direct channels | ✓ | ✓ |
| Threaded replies | ✓ (1 level) | ✓ (multi-level) |
| Emoji reactions | ✓ | ✓ |
| Unread count per member | ✓ | ✓ |
| Message search | ✗ | ✓ |
| @mentions / notifications | ✗ | ✓ |
| File attachments in messages | ✓ (JSONB list) | ✓ (binary) |
| Video/audio calls | ✗ | ✓ (Jitsi) |
| Bot / command messages | ✗ | partial |
| BPM-linked system channels | ✓ | ✓ (chatter) |
| Message edit / soft delete | ✓ (is_deleted flag) | ✓ |

## Benchmark: Slack

| Feature | Ours | Slack |
|---|---|---|
| Channel types | ✓ | ✓ |
| Multi-level threads | ✗ | ✓ |
| Slash commands | ✗ | ✓ |
| App integrations (webhooks) | ✗ | ✓ (1000+) |
| Message search | ✗ | ✓ |
| Voice/video | ✗ | ✓ |
| ERP record linking | ✓ first-class | ✗ |
| Transactional event delivery | ✓ (same DB txn) | ✗ |
| No per-seat pricing | ✓ | ✗ |

---

## Differentiation

**Where we exceed:**
- System channels are created automatically by BPM steps and scoped to `(module, record_id)` — every workflow instance gets a purpose-built audit trail channel without developer effort
- Notification delivery is atomic with the business mutation (same session, same transaction)
- No external messaging infrastructure required; works entirely within PostgreSQL

**Remaining gaps:**
- No full-text message search
- Single-level threading only
- No @mentions or push notifications
- No rich media support beyond stored attachment metadata
- No presence / online status
