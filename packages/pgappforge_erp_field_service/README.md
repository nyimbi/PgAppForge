# pgappforge-erp-field-service

**Field Service — work orders, scheduling, dispatching, mobile workforce, parts**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-field-service
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_field_service import FieldServicePlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = FieldServicePlugin(appbuilder)
plugin.activate()
```

## Features

- Field work order lifecycle
- Technician scheduling and dispatch
- Parts reservation and consumption
- Mobile check-in and signature capture
- SLA-driven priority queuing

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
