# Tutorial 07: Connecting to Slack

The Integration Hub provides outbound webhooks (trigger on database events → call an external URL), inbound webhooks (receive an HTTP POST from an external system), and OAuth 2.0 connector management. This tutorial connects to Slack so your team gets notified when a new AR invoice is created.

## Prerequisites

- A running pgappforge app (see [Tutorial 02](02_first_app_from_db.md))
- A Slack workspace where you can create a Slack App
- The `ar` template applied to your database (see [Tutorial 03](03_using_templates.md))

## Step 1 — Enable IntegrationHubPlugin

```python
# app.py
from pgappforge.plugins.integrations import IntegrationHubPlugin

def create_app():
    app = Flask(__name__)
    # ... other setup ...
    appbuilder = AppBuilder(app, db.session)

    hub = IntegrationHubPlugin()
    hub.initialize(app, appbuilder)
    hub.register_views(appbuilder)

    return app
```

Restart the app. **Integration Hub** appears in the **Tools** menu.

## Step 2 — Navigate to Integration Hub

Go to `http://127.0.0.1:5000/integrationhub/`. You see three tabs:

- **Connectors** — available and active integrations
- **Webhooks** — outbound and inbound webhook configuration
- **Monitor** — recent webhook deliveries with status codes and response bodies

## Step 3 — Add the Slack Integration

1. Click the **Slack** card in the Connectors panel.
2. A configuration dialog opens. Paste your Slack Bot OAuth token (`xoxb-...`).
3. Enter the default channel where notifications should be sent (e.g. `#finance-alerts`).
4. Click **Save**. The Slack card status dot turns green: **Active**.

If you do not yet have a Slack Bot token:

1. Go to `https://api.slack.com/apps` → **Create New App** → **From scratch**
2. Under **OAuth & Permissions**, add the `chat:write` scope
3. Install the app to your workspace
4. Copy the **Bot User OAuth Token** (`xoxb-...`)

## Step 4 — Create an Outbound Webhook: Invoice → Slack

1. Click the **Webhooks** tab → **+ Outbound Webhook**.
2. Fill in the form:

| Field | Value |
|-------|-------|
| Name | Invoice created — Slack alert |
| Trigger table | `ar_invoice` |
| Trigger event | `INSERT` |
| Integration | Slack (the one you just configured) |
| Message template | `New invoice {{invoice_number}} for {{customer_name}} — {{currency}} {{total_amount}}` |
| Channel | `#finance-alerts` |

3. Click **Save**.

The template supports `{{column_name}}` placeholders. The Integration Hub resolves them from the inserted row's column values at delivery time. FK columns (like `customer_id`) are automatically joined to show the display value (`customer_name`) if the FK target table is in the same schema.

## Step 5 — Test by Creating an Invoice

In the pgappforge UI go to **Accounts Receivable → Invoices → Add**. Fill in the required fields (customer, invoice number, total amount, currency) and save.

Within a second or two, the Slack message fires:

```
New invoice INV-2024-001 for Acme Corp — USD 4,250.00
```

Check the **Monitor** tab in Integration Hub to confirm delivery:

```
2024-01-15 14:23:07  ar_invoice INSERT  Slack #finance-alerts  200 OK  12ms
```

If delivery fails (network error, invalid token) the Monitor shows the HTTP status code and error body. Failed deliveries are retried up to three times with exponential back-off.

## Step 6 — Create an Inbound Webhook for Slack Slash Commands

You can expose an inbound webhook URL that Slack can call when a user runs a slash command.

1. In the **Webhooks** tab click **+ Inbound Webhook**.
2. Give it a name: "Slack /invoice command"
3. Set **Secret key** — the Hub uses this to verify the `X-Slack-Signature` HMAC header.
4. Click **Save**.

The Hub generates a URL:

```
https://your-domain.com/webhooks/receive/a3f9c2b1-d4e8-4056-8f3a-7b2c1d9e0f1a
```

In your Slack App settings:

1. Go to **Slash Commands** → **Create New Command**
2. Command: `/invoice`
3. Request URL: paste the inbound webhook URL above
4. Click **Save**

Now when a Slack user runs `/invoice status INV-2024-001`, Slack POSTs to your inbound webhook. The Hub verifies the signature, logs the delivery, and fires any configured response actions (e.g. querying the `ar_invoice` table and posting the result back to Slack via the outbound connector).

## Available Connectors

The Integration Hub ships with pre-built connector configurations for:

- **Slack** — `chat:write`, `channels:read`, incoming webhooks
- **Stripe** — payment event webhooks
- **HubSpot** — contact and deal sync
- **Salesforce** — opportunity and account sync (OAuth 2.0)
- **Generic REST** — any HTTP endpoint with configurable headers, auth, and body template

## Next Steps

- Add a webhook on `ar_payment INSERT` to trigger an invoice-paid Slack notification
- Use the **Monitor** tab to debug failed deliveries — it shows the full request payload and response body
- Chain two webhooks: on `crm_opportunity` stage change → update `ar_invoice` status → fire Slack alert
