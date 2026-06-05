# pgappforge-erp-service

**Customer Service — cases, SLA, knowledge base, escalation, satisfaction surveys**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-service
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_service import ServicePlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = ServicePlugin(appbuilder)
plugin.activate()
```

## Features

- Case and ticket management
- SLA definition and breach alerting
- Knowledge base articles
- Escalation rules and routing
- Customer satisfaction (CSAT) surveys

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
