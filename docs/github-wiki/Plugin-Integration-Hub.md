# Plugin: Integration Hub

[Home](Home) > Plugin: Integration Hub

The Integration Hub plugin connects pgappforge applications to external systems via OAuth 2.0, REST, GraphQL, and webhooks. Pre-built connectors are provided for Stripe, Salesforce, HubSpot, and Slack.

---

## Initialisation

```python
from pgappforge.plugins.integrations import IntegrationHubPlugin

plugin = IntegrationHubPlugin()
plugin.initialize(app, appbuilder)
plugin.register_views(appbuilder)
```

Registers:
- `IntegrationHubView` at `/tools/integration-hub/` — connection management UI
- `WebhookReceiverView` (no menu) — inbound webhook endpoint at `/webhooks/receive/<connector>/`

---

## Capabilities

### OAuth 2.0 Connectors

Configure OAuth credentials in the UI. The hub stores tokens encrypted at rest using the key in `FAB_INTEGRATION_ENCRYPTION_KEY`. Supports token refresh automatically before expiry.

### REST / GraphQL

Add any REST or GraphQL endpoint as a named integration. Define request templates (headers, body, auth) and trigger them from view actions, scheduled jobs, or webhook receipt.

### Webhook Outbound

Register outbound webhook targets per event type. Failed deliveries are retried up to `FAB_INTEGRATION_WEBHOOK_RETRY_MAX` times with exponential back-off. Allowed destinations are validated against `FAB_RULES_WEBHOOK_ALLOWLIST`.

### Pre-built Connectors

| Connector | Auth | Events supported |
|---|---|---|
| Stripe | OAuth / API key | payment.succeeded, invoice.paid, customer.created |
| Salesforce | OAuth 2.0 | Lead, Contact, Opportunity CRUD |
| HubSpot | OAuth 2.0 | Contact, Deal, Company CRUD |
| Slack | OAuth 2.0 | Message send, channel events |

---

## Configuration

| Key | Default | Description |
|---|---|---|
| `FAB_INTEGRATION_ENCRYPTION_KEY` | Required | Fernet key for encrypting stored OAuth tokens |
| `FAB_INTEGRATION_WEBHOOK_RETRY_MAX` | `5` | Maximum outbound webhook delivery attempts |
| `FAB_RULES_WEBHOOK_ALLOWLIST` | `[]` | Allowed outbound webhook URL prefixes |

---

## Further Reading

Full reference: [docs/plugins/integrations.md](../plugins/integrations.md)

---

## See also

- [Plugin: Realtime](Plugin-Realtime)
- [Plugin: Audit Trail](Plugin-Audit-Trail)
- [Architecture](Architecture)
- [Configuration Reference](../api/configuration.md)
