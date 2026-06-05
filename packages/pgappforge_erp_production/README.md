# pgappforge-erp-production

**Production Planning — BOMs, work orders, routing, capacity, shop-floor control**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-production
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_production import PPPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = PPPlugin(appbuilder)
plugin.activate()
```

## Features

- Bill of Materials (multi-level)
- Production work order lifecycle
- Routing and work centre management
- Capacity planning and scheduling
- Shop-floor data collection

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
