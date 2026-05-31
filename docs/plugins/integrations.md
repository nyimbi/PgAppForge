# Integration Hub

The Integration Hub gives any pgappforge application a unified connectivity layer for exchanging data, events, and triggers with external systems. It ships a dark-themed management UI, an AES-256-GCM encrypted credential vault, an HMAC-verified inbound webhook receiver, and a plugin-based connector registry — without requiring per-integration bespoke code.

Ten connectors are included out of the box (Slack, Stripe, Salesforce, HubSpot, GitHub, Google Workspace, Twilio, Microsoft Teams, Generic REST, Generic GraphQL). Additional connectors are registered via Python entry points and discovered at runtime.

## Quick Start

```python
from pgappforge.plugins.integrations import IntegrationHubPlugin

# config.py
PGAPPFORGE_PLUGINS = ["pgappforge.plugins.integrations.IntegrationHubPlugin"]

FAB_INTEGRATION_ENCRYPTION_KEY = os.environ["FAB_INTEGRATION_ENCRYPTION_KEY"]  # required
FAB_INTEGRATION_WEBHOOK_RETRY_MAX = 10

def create_app():
    app = Flask(__name__)
    appbuilder = AppBuilder(app, db.session)

    plugin = IntegrationHubPlugin()
    plugin.initialize(app, appbuilder)
    plugin.register_views(appbuilder)   # mounts /integration-hub/ and the inbound receiver

    return app
```

Run migrations to create the four plugin tables:

```bash
flask db migrate -m "add integration hub tables"
flask db upgrade
```

To rotate credentials after a key change:

```bash
flask fab rotate-integration-keys
```

## Configuration Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `FAB_INTEGRATION_ENCRYPTION_KEY` | `str` | — | **Required.** AES-256-GCM key for credential vault. 32+ characters recommended. |
| `FAB_INTEGRATION_WEBHOOK_RETRY_MAX` | `int` | `10` | Maximum delivery attempts before marking a webhook event permanently failed |
| `FAB_INTEGRATION_WEBHOOK_RATE_LIMIT` | `str` | `"120/minute"` | Flask-Limiter rate limit string for inbound webhook endpoints |
| `FAB_INTEGRATION_ALERT_RECIPIENTS` | `list[str]` | `[]` | Email addresses for integration error alerts (requires ReportForge plugin) |
| `FAB_INTEGRATION_OAUTH_REDIRECT_BASE` | `str` | auto | Base URL for the OAuth callback (`/integration-hub/oauth/callback`) |
| `FAB_INTEGRATION_SYNC_WORKERS` | `int` | `2` | Number of background sync worker threads |
| `FAB_INTEGRATION_SALESFORCE_API_VERSION` | `str` | `"v59.0"` | Salesforce REST API version |
| `FAB_INTEGRATION_GOOGLE_SCOPES` | `list[str]` | Sheets + Calendar + Contacts | OAuth scopes requested from Google |

## Key API / Endpoints

Authenticated management endpoints (all require `@has_access`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/integration-hub/` | Management UI — connectors, webhooks, monitor tab |
| `POST` | `/integration-hub/api/integrations` | Create a new integration (connector type + config + credentials) |
| `GET` | `/integration-hub/api/integrations/<id>/test` | Test the connection; returns `{"ok": bool, "message": str}` |
| `GET` | `/integration-hub/oauth/start/<intg_id>` | Start OAuth 2.0 authorization code flow |
| `GET` | `/integration-hub/oauth/callback` | OAuth callback — exchanges code, encrypts and stores tokens |
| `POST` | `/integration-hub/api/webhooks` | Create an outbound or inbound webhook configuration |
| `GET` | `/integration-hub/api/events` | List 50 most recent `IntegrationEvent` rows for monitoring |
| `POST` | `/integration-hub/api/events/<id>/retry` | Reset a failed event to `retrying` with `next_retry_at = now()` |

Public unauthenticated inbound endpoint:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/integrations/webhooks/in/<token>` | Inbound webhook receiver — HMAC verification, payload transform, dispatch |

Signature verification supports `X-Hub-Signature-256` (GitHub/generic), `Stripe-Signature`, and `X-Slack-Signature`. Replay-attack prevention rejects requests older than 300 seconds. Rate limits: 120 req/min per token, 300 req/min per IP (global 1000 req/s).

## Example Usage

```python
# --- Register a custom connector ---
from pgappforge.plugins.integrations import IntegrationHubPlugin
from pgappforge.plugins.integrations.connectors.base import BaseConnector

class MyERPConnector(BaseConnector):
    name         = "my_erp"
    display_name = "My ERP"
    icon         = "fa-building"
    auth_types   = ["api_key"]

    def test_connection(self) -> dict:
        resp = requests.get(
            f"{self.config['base_url']}/health",
            headers={"X-Api-Key": self.credentials["api_key"]},
            timeout=5,
        )
        return {"ok": resp.ok, "message": resp.reason}

IntegrationHubPlugin.register_connector(MyERPConnector)

# --- Register a custom action type ---
from pgappforge.plugins.integrations.event_mapper import EventMapper

@EventMapper.action("send_push_notification")
def send_push(context: dict, config: dict) -> None:
    # config contains action-specific keys set in the event mapping UI
    ...

# --- Outbound webhook configuration (stored in pgaf_webhook) ---
outbound_config = {
    "events": ["model_insert", "model_update"],
    "model_name": "Order",
    "filter": "record.status == 'shipped'",
}
# Payload and headers are Jinja2 templates:
# payload_template: '{"order_id": "{{ record.id }}", "ts": "{{ timestamp }}"}'

# --- Inbound webhook dispatches a model_create action ---
trigger_config = {
    "action": "model_create",
    "model_name": "Order",
    "action_config": {
        "field_map": {
            "customer_email": "{{ payload.data.object.customer_email }}",
            "amount_cents":   "{{ payload.data.object.amount }}"
        }
    }
}
```

Credential vault details: key is SHA-256 hashed to produce a 32-byte AES key; each blob uses a unique 12-byte random nonce; AES-256-GCM provides authenticated encryption. `encrypt_credentials()` raises `RuntimeError` if `FAB_INTEGRATION_ENCRYPTION_KEY` is absent, preventing silent plaintext storage.

Outbound webhook retry schedule: `30 s → 1 m → 2 m → 4 m → 8 m → 16 m → 32 m → 1 h → 2 h → 4 h` (up to `FAB_INTEGRATION_WEBHOOK_RETRY_MAX` attempts). After max retries, `status = "failed"` and an alert is dispatched via ReportForge if configured.

## See Also

- [Realtime plugin](realtime.md) — SQLAlchemy model-change events that can also trigger outbound webhooks
- [Forms plugin](forms.md) — form `post_submit_actions` can invoke Integration Hub connectors
- [Audit plugin](audit.md) — all `IntegrationEvent` rows are themselves auditable via `AuditMixin`
- pgappforge SPEC: `pgappforge/plugins/integrations/SPEC.md`
