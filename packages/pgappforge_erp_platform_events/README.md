# pgappforge-erp-platform-events

**Platform Events — event bus, pub/sub routing, webhook delivery, audit log**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-platform-events
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_platform_events import PlatformEventsPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = PlatformEventsPlugin(appbuilder)
plugin.activate()
```

## Features

- In-process pub/sub event bus
- Webhook endpoint registration and delivery
- Event replay and dead-letter queue
- Per-event audit log
- Schema versioning for event payloads

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
