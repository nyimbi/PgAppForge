# Integration Hub

## Overview

Every generated pgappforge application risks becoming an island — isolated CRUD with no connection to the broader software ecosystem a business actually runs. The Integration Hub solves this by providing a unified, plugin-based connectivity layer that lets any pgappforge app exchange data, events, and triggers with external systems without writing bespoke integration code each time.

The hub ships as `pgappforge.plugins.integrations` and is activated via `PGAPPFORGE_PLUGINS`. Once active it:

- Provides a dark-themed UI at `/integration-hub/` for managing connectors, webhooks, and monitoring
- Persists all configuration to four PostgreSQL tables (`pgaf_integration`, `pgaf_integration_credential`, `pgaf_webhook`, `pgaf_integration_event`)
- Encrypts all secrets at rest using AES-256-GCM
- Exposes a JSON REST micro-API for the UI and for programmatic access

---

## Connector Registry

### Plugin-Based Architecture

Connectors are Python classes that extend `BaseConnector`. They are discovered at runtime from any installed package that registers the entry point group `pgappforge.integrations.connectors`. First-party connectors ship inside `pgappforge/plugins/integrations/connectors/`.

Registration example in `setup.cfg` / `pyproject.toml`:

```toml
[project.entry-points."pgappforge.integrations.connectors"]
slack   = "pgappforge.plugins.integrations.connectors.slack:SlackConnector"
stripe  = "pgappforge.plugins.integrations.connectors.stripe:StripeConnector"
my_erp  = "my_company.integrations.erp:ERPConnector"
```

The `ConnectorRegistry` singleton loads all entry points at startup and caches connector classes by `name`. The UI reads the registry to populate the "Available Connectors" grid.

### `BaseConnector` ABC

```python
class BaseConnector(ABC):
    name: str             # connector identifier, e.g. "stripe"
    display_name: str     # human label, e.g. "Stripe"
    icon: str             # FontAwesome class, e.g. "fa-cc-stripe"
    auth_types: list[str] # supported: oauth2 / api_key / basic / bearer

    def __init__(self, config: dict, credentials: dict): ...

    @abstractmethod
    def test_connection(self) -> dict:
        """Returns {"ok": bool, "message": str}"""

    def list_objects(self) -> list[str]:
        """Syncable object types, e.g. ["Contact", "Opportunity"]"""

    def get_object_schema(self, object_type: str) -> list[dict]:
        """Field schema: [{name, type, required, label}]"""

    def sync_to_external(self, object_type: str, record: dict) -> dict:
        """Push one record. Returns {"external_id": str, "status": str}"""

    def sync_from_external(self, object_type: str, since_cursor=None) -> list[dict]:
        """Pull records since cursor."""

    def handle_webhook(self, headers: dict, body: bytes) -> dict:
        """Verify signature, parse body. Returns {"event_type": str, "data": dict}"""

    @classmethod
    def get_oauth_authorize_url(cls, config: dict, redirect_uri: str, state: str) -> str: ...

    @classmethod
    def exchange_oauth_code(cls, config: dict, code: str, redirect_uri: str) -> dict: ...
```

### Built-In Connectors

| Connector | `name` | Auth Types | Objects | Push | Pull | Webhooks |
|-----------|--------|-----------|---------|------|------|----------|
| Slack | `slack` | oauth2, bearer | channels, users | send_message | — | slash_command, event |
| Stripe | `stripe` | api_key | customer, subscription, invoice, product | create/update | list | payment_intent, invoice, subscription |
| Salesforce | `salesforce` | oauth2 | Contact, Account, Opportunity, Lead | create/update/upsert | query | push_topic |
| HubSpot | `hubspot` | oauth2, api_key | Contact, Company, Deal, Ticket | create/update | list | contact.creation, deal.stageChange |
| GitHub | `github` | oauth2, bearer | repo, issue, PR, release | create issue/comment | list | push, issues, pull_request |
| Google Workspace | `google` | oauth2 | Sheet, Calendar Event, Contact | append/update | read | — |
| Twilio | `twilio` | api_key | sms, call | send_sms | — | inbound_sms |
| Microsoft Teams | `teams` | oauth2, bearer | channel, message | send_message | — | — |
| Generic REST | `rest` | api_key, bearer, basic, oauth2 | user-defined | yes | yes | — |
| Generic GraphQL | `graphql` | api_key, bearer | user-defined | yes | yes | — |

---

## OAuth 2.0 Flow Manager

The `OAuthFlowManager` handles the complete authorization dance for connectors that use OAuth 2.0. It is stateless from the app's perspective — state is persisted in `pgaf_integration_credential`.

### Authorization Code Flow

Used by: Stripe (Connect), Salesforce, HubSpot, Google Workspace, GitHub, Slack

Flow:

1. User clicks "Connect" in the UI → `GET /integration-hub/oauth/start/<intg_id>`
2. Manager generates a cryptographically random `state` token (stored in session)
3. Redirects user to `connector.get_oauth_authorize_url(config, redirect_uri, state)`
4. Provider redirects back to `GET /integration-hub/oauth/callback`
5. Manager validates `state`, calls `connector.exchange_oauth_code(config, code, redirect_uri)`
6. Received `{access_token, refresh_token, expires_in, ...}` is encrypted via `encrypt_credentials()` and written to `pgaf_integration_credential`
7. `Integration.status` → `"active"`

Token refresh is automatic: before any API call, the manager checks `expires_at`; if within 60 seconds it calls the provider's token endpoint using `refresh_token` and updates the stored credential.

### Client Credentials Flow

Used by: machine-to-machine services (custom REST connectors that support it)

```
POST /token
  grant_type=client_credentials
  client_id=...
  client_secret=...
  scope=...
```

The manager handles this transparently when `auth_type = "oauth2_client_credentials"`.

### API Key and Bearer Token

Simple credential types stored in `pgaf_integration_credential` as `{"api_key": "..."}` or `{"bearer_token": "..."}`. The connector receives the decrypted dict in `self.credentials`.

### Credential Vault

All credentials are stored encrypted using AES-256-GCM via `pgappforge.plugins.integrations.encryption`:

- **Key derivation**: SHA-256 hash of `FAB_INTEGRATION_ENCRYPTION_KEY` → 32-byte AES key
- **Nonce**: 12 random bytes prepended to ciphertext
- **Authentication tag**: 16 bytes appended by AESGCM (included in ciphertext blob)
- **Storage**: `base64(nonce + ciphertext_with_tag)` in `pgaf_integration_credential.encrypted_data` (LargeBinary)
- **At-rest**: Never stored in plaintext anywhere; config values never logged

Rotation: supply a new `FAB_INTEGRATION_ENCRYPTION_KEY` and run `flask fab rotate-integration-keys` (re-encrypts all credentials with the new key).

---

## Generic REST/GraphQL Connector

The `rest` connector type provides a no-code API builder for arbitrary REST (and GraphQL) backends without writing a custom connector class.

### No-Code API Builder

Configured entirely via the `Integration.config` JSONB column:

```json
{
  "base_url": "https://api.example.com/v2",
  "auth_type": "bearer",
  "objects": {
    "order": {
      "list_endpoint": "/orders",
      "list_method": "GET",
      "list_params": {"status": "active", "limit": 100},
      "create_endpoint": "/orders",
      "create_method": "POST",
      "id_field": "id",
      "pagination": {"type": "cursor", "cursor_field": "next_cursor", "cursor_param": "cursor"}
    }
  }
}
```

### Jinja2 Request Templates

Request bodies and headers can be templated:

```jinja2
{
  "contact": {
    "email": "{{ record.email }}",
    "name": "{{ record.first_name }} {{ record.last_name }}",
    "created_at": "{{ now().isoformat() }}"
  }
}
```

Variables available in templates: `record` (the pgappforge model dict), `integration` (the Integration row), `env` (safe subset of `app.config`), `now()`.

### JSONPath Response Mapping

Map external response fields to pgappforge model fields using JSONPath expressions:

```json
{
  "field_map": {
    "external_id": "$.data.id",
    "email": "$.data.attributes.email",
    "items": "$.data.relationships.orders[*].id"
  }
}
```

Uses the `jsonpath-ng` library. Arrays are joined with `,` by default; override with `"join": false` to get a list.

### Pagination Auto-Detection

The REST connector inspects response envelopes and auto-detects common pagination schemes:

| Scheme | Detection | Mechanism |
|--------|-----------|-----------|
| `offset` | `total`, `offset`, `limit` keys | Increment offset until `offset + limit >= total` |
| `cursor` | `next_cursor` or `next_page_token` key | Follow until null/empty |
| `link_header` | `Link: <url>; rel="next"` header | Follow until no next link |
| `page` | `page`, `per_page`, `total_pages` | Increment until `page >= total_pages` |
| `none` | Single-page response | Return as-is |

Override auto-detection by setting `"pagination": {"type": "offset"}` in `objects.<name>`.

---

## Webhook Registry

### Inbound Webhooks

Each inbound webhook gets a unique URL:

```
POST /integrations/webhooks/in/<token>
```

Where `<token>` is a 32-byte URL-safe random string stored in `WebhookEndpoint.token`. The full URL is shown in the UI and is suitable for pasting into provider dashboards (Stripe, GitHub, Slack, etc.).

**HMAC Signature Verification**

When `WebhookEndpoint.verify_signature = True` and a `secret` is set:

1. The receiver reads the provider-specific signature header (`X-Hub-Signature-256` for GitHub, `Stripe-Signature` for Stripe, `X-Slack-Signature` for Slack, or `X-Hub-Signature-256` as a generic fallback)
2. Computes `HMAC-SHA256(secret, body)` and compares in constant time via `hmac.compare_digest`
3. Returns `401 Unauthorized` if the signature does not match

**Payload Transformation**

The `trigger_config.transform` key accepts a Jinja2 template that reshapes the incoming payload before dispatch:

```json
{
  "action": "model_create",
  "model_name": "Order",
  "action_config": {
    "field_map": {
      "customer_email": "{{ payload.data.object.customer_email }}",
      "amount_cents": "{{ payload.data.object.amount }}"
    }
  },
  "transform": "..."
}
```

**Dispatch Actions**

After verification and transformation, the receiver dispatches based on `trigger_config.action`:

| Action | Description |
|--------|-------------|
| `model_create` | Create a record in `model_name` with mapped fields |
| `model_update` | Update a record found by `lookup_field` |
| `rules` | Fire the Rules Engine with `rule_id` and extracted context |
| `bpm` | Start a BPM workflow instance |
| `custom` | Call a registered Python callable |

### Outbound Webhooks

Outbound webhooks fire when pgappforge model events occur (insert, update, delete). Configuration:

```json
{
  "events": ["model_insert", "model_update"],
  "model_name": "Order",
  "filter": "record.status == 'shipped'"
}
```

**Delivery**

1. SQLAlchemy `after_flush` event triggers the outbound dispatcher
2. Dispatcher renders the Jinja2 `payload_template` with `{record, event_type, timestamp}`
3. Also renders `headers_template` to produce request headers
4. HTTP POST to `WebhookEndpoint.url` with 10-second timeout
5. `IntegrationEvent` row created with request/response details

**Retry with Exponential Backoff**

On failure (non-2xx or network error):

- Retry schedule: `30s → 1m → 2m → 4m → 8m → 16m → 32m → 1h → 2h → 4h` (up to `FAB_INTEGRATION_WEBHOOK_RETRY_MAX` attempts, default 10)
- `next_retry_at` is set on the `IntegrationEvent` row; a background worker (Celery task or APScheduler job) polls for due retries
- After max retries, `status = "failed"` and an alert is dispatched via ReportForge if configured

---

## Event Mapping

The Event Mapper provides a simple "When → Do" pipeline, letting non-developers wire together triggers and actions through the UI.

### Trigger Types

| Trigger | Source | Config Keys |
|---------|--------|-------------|
| `inbound_webhook` | WebhookEndpoint | `webhook_id` |
| `model_insert` | SQLAlchemy event | `model_name`, `filter` |
| `model_update` | SQLAlchemy event | `model_name`, `fields`, `filter` |
| `schedule` | APScheduler / Celery beat | `rrule` |
| `manual` | UI button / API call | — |
| `integration_sync` | Connector pull | `integration_id`, `object_type` |

### Action Types

| Action | Target | Config Keys |
|--------|--------|-------------|
| `send_outbound_webhook` | External URL | `webhook_id` |
| `create_record` | pgappforge model | `model_name`, `field_map` |
| `update_record` | pgappforge model | `model_name`, `lookup_field`, `field_map` |
| `send_slack_message` | Slack connector | `integration_id`, `channel`, `message_template` |
| `send_sms` | Twilio connector | `integration_id`, `to`, `body_template` |
| `fire_rules` | Rules Engine | `rule_id`, `context_map` |
| `start_workflow` | BPM Engine | `workflow_id`, `input_map` |
| `notify_report` | ReportForge dispatch | `report_id`, `recipients` |

Each mapping is a JSON document stored in the `trigger_config` column of an auxiliary `pgaf_event_mapping` table (Phase 2).

---

## Sync Monitoring

### Connection Health Dashboard

Available at `/integration-hub/` → Monitor tab. Shows:

- **Overall status**: count of active / error / paused integrations
- **Per-integration**: last sync time, last sync status, error message preview, sync duration trend
- **Delivery rate**: success % over last 24h / 7d / 30d per webhook

### Error Rates and Retry Queues

The monitor polls `GET /integration-hub/api/events` which returns the 50 most recent `IntegrationEvent` rows. Columns displayed:

| Column | Description |
|--------|-------------|
| Direction | inbound / outbound |
| Webhook | Name of the WebhookEndpoint |
| Status | delivered / failed / retrying / pending |
| Attempts | `attempt_count` |
| Response | HTTP status code |
| Time | `created_at` |

A "Retry Now" button on failed events calls `POST /integration-hub/api/events/<id>/retry`, which resets `next_retry_at = now()` and `status = "retrying"`.

### Alerting via ReportForge Dispatch

When a connector enters `status = "error"` or a webhook exceeds max retries, the Integration Hub calls `ReportForgeDispatch.send_alert()` (if the reports plugin is active) with:

```python
{
    "subject": "Integration error: {integration.name}",
    "body": "...",
    "recipients": app.config.get("FAB_INTEGRATION_ALERT_RECIPIENTS", []),
}
```

---

## Pre-Built Connectors

### Stripe

```
connector_type = "stripe"
auth_types = ["api_key"]
```

**Objects**: `customer`, `subscription`, `invoice`, `product`, `price`

**Sync Operations**:
- Pull customers → `pgaf_billing_customer` (or custom model via `config.target_model`)
- Push customer updates from pgappforge → Stripe via `stripe.Customer.modify()`
- Bidirectional subscription status sync

**Payment Webhooks**:
- `payment_intent.succeeded` → mark order paid, trigger BPM
- `invoice.payment_failed` → trigger dunning workflow
- `customer.subscription.deleted` → deactivate tenant subscription
- `customer.subscription.updated` → sync plan changes

Signature verification uses `stripe.Webhook.construct_event()` with `PGAF_BILLING_STRIPE_WEBHOOK_SECRET`.

### Salesforce

```
connector_type = "salesforce"
auth_types = ["oauth2"]
```

**Objects**: `Contact`, `Account`, `Opportunity`, `Lead`, `Task`

**Sync Operations**:
- Bidirectional Contact ↔ pgappforge user/contact model using SOQL queries
- Opportunity stage changes trigger pgappforge workflow
- Uses the Salesforce REST API v59.0+ and `simple-salesforce` library

**Webhook (Push Topics)**:
Salesforce Streaming API push topics are polled via CometD. Requires `FAB_INTEGRATION_SALESFORCE_PUSH_TOPIC = True`.

### Slack / Microsoft Teams

```
connector_type = "slack" | "teams"
auth_types = ["oauth2", "bearer"]
```

**Outbound Notifications**:
- Send messages to channels via `chat.postMessage` (Slack) or Graph API (Teams)
- Block Kit support for Slack (rich interactive messages)
- Adaptive Cards support for Teams

**Inbound Slash Commands (Slack)**:
- Receive `POST /integrations/webhooks/in/<token>` from Slack
- Payload type `url_verification` auto-handled (returns challenge)
- `slash_commands` type dispatched to Rules Engine or BPM

### Google Workspace

```
connector_type = "google"
auth_types = ["oauth2"]
scopes = "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/contacts"
```

**Sheets Export**: Append or overwrite rows in a Google Sheet from any ModelView queryset. Config: `{spreadsheet_id, sheet_name, range}`.

**Calendar Sync**: Create/update Google Calendar events from pgappforge scheduling models.

**Contacts Sync**: Bidirectional sync between pgappforge user records and Google Contacts (People API v1).

### Twilio

```
connector_type = "twilio"
auth_types = ["api_key"]
```

**SMS Triggers**:
- `send_sms(to, body)` — called from Rules Engine, BPM actions, or outbound webhook dispatch
- Inbound SMS via webhook — parsed and dispatched to `trigger_config.action`
- Delivery status callbacks update `IntegrationEvent`

---

## Security

### Credential Encryption

All OAuth tokens, API keys, and secrets are encrypted before persistence:

1. `FAB_INTEGRATION_ENCRYPTION_KEY` is required in app config (minimum 32 characters recommended)
2. Key is hashed with SHA-256 to produce a deterministic 32-byte AES key
3. Each credential blob uses a unique 12-byte random nonce
4. AES-256-GCM provides both confidentiality and authenticity (256-bit key, 128-bit tag)
5. Decryption fails loudly (raises `InvalidTag`) if ciphertext has been tampered with

The `cryptography` package (PyCA) is used exclusively — no OpenSSL bindings or custom crypto.

If `FAB_INTEGRATION_ENCRYPTION_KEY` is not set, `encrypt_credentials()` raises `RuntimeError` at call time to prevent silent plaintext storage.

### Webhook Signature Verification

Inbound webhooks use `hmac.compare_digest` (constant-time) for all signature comparisons. Supported schemes:

| Header | Format | Used By |
|--------|--------|---------|
| `X-Hub-Signature-256` | `sha256=<hex>` | GitHub, generic |
| `Stripe-Signature` | `t=<ts>,v1=<hex>` | Stripe |
| `X-Slack-Signature` | `v0=<hex>` | Slack |

Timestamps are checked for replay-attack prevention: requests older than 300 seconds are rejected.

### Rate Limiting on Inbound Webhooks

The `WebhookReceiverView` applies per-token rate limiting using a sliding window counter stored in Redis (if `CACHE_TYPE = "RedisCache"`) or in-process (fallback). Default limits:

| Scope | Limit |
|-------|-------|
| Per token per minute | 120 requests |
| Per IP per minute | 300 requests |
| Global per second | 1000 requests |

Configure via `FAB_INTEGRATION_WEBHOOK_RATE_LIMIT = "120/minute"` (uses Flask-Limiter syntax).

---

## Configuration Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `FAB_INTEGRATION_ENCRYPTION_KEY` | `str` | — | **Required.** AES-256-GCM key for credential vault. Min 32 chars recommended. |
| `FAB_INTEGRATION_WEBHOOK_RETRY_MAX` | `int` | `10` | Maximum delivery attempts before marking a webhook event as permanently failed. |
| `FAB_INTEGRATION_WEBHOOK_RATE_LIMIT` | `str` | `"120/minute"` | Flask-Limiter rate limit string for inbound webhook endpoints. |
| `FAB_INTEGRATION_ALERT_RECIPIENTS` | `list[str]` | `[]` | Email addresses for integration error alerts (requires ReportForge). |
| `FAB_INTEGRATION_OAUTH_REDIRECT_BASE` | `str` | auto | Base URL for OAuth callback (`/integration-hub/oauth/callback`). |
| `FAB_INTEGRATION_SYNC_WORKERS` | `int` | `2` | Number of background sync worker threads. |
| `FAB_INTEGRATION_SALESFORCE_API_VERSION` | `str` | `"v59.0"` | Salesforce REST API version. |
| `FAB_INTEGRATION_GOOGLE_SCOPES` | `list[str]` | see above | OAuth scopes requested from Google. |

### Activation

```python
# config.py
PGAPPFORGE_PLUGINS = [
    "pgappforge.plugins.tenancy.TenancyPlugin",
    "pgappforge.plugins.billing.BillingPlugin",
    "pgappforge.plugins.integrations.IntegrationHubPlugin",
]

FAB_INTEGRATION_ENCRYPTION_KEY = os.environ["FAB_INTEGRATION_ENCRYPTION_KEY"]
FAB_INTEGRATION_WEBHOOK_RETRY_MAX = 10
```

### Alembic Migration

The plugin's `register_models()` returns all four model classes so that `flask db migrate` picks them up automatically via the standard pgappforge Alembic integration.

---

## Extension Points

### Writing a Custom Connector

1. Subclass `BaseConnector`
2. Implement at minimum `test_connection()`
3. Register via entry points or pass the class directly:

```python
from pgappforge.plugins.integrations import IntegrationHubPlugin

IntegrationHubPlugin.register_connector(MyERPConnector)
```

### Adding Custom Trigger/Action Types

Register handlers in the `EventMapper` registry:

```python
from pgappforge.plugins.integrations.event_mapper import EventMapper

@EventMapper.action("send_push_notification")
def send_push(context: dict, config: dict) -> None:
    ...
```

### Connector Lifecycle Hooks

Connectors can implement optional hooks:

```python
def on_sync_start(self, object_type: str) -> None: ...
def on_sync_complete(self, object_type: str, count: int) -> None: ...
def on_sync_error(self, object_type: str, exc: Exception) -> None: ...
```

---

## Roadmap

| Phase | Feature |
|-------|---------|
| 1 (current) | Core models, encryption vault, Slack connector, inbound/outbound webhooks, monitoring UI |
| 2 | Event mapper UI, REST/GraphQL no-code builder, Stripe + Salesforce connectors |
| 3 | OAuth flow manager UI, token auto-refresh, Google Workspace connector |
| 4 | Twilio, HubSpot, GitHub connectors; rate limiting; Celery retry worker |
| 5 | Bidirectional field mapping UI, ReportForge alerting integration, connector SDK docs |
