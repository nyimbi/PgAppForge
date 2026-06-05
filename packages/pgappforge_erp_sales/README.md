# pgappforge-erp-sales

**Sales — leads, opportunities, pipeline, quotes, orders, forecasting**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-sales
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_sales import SalesPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = SalesPlugin(appbuilder)
plugin.activate()
```

## Features

- Lead and opportunity management
- Sales pipeline and stage tracking
- Quote and proposal generation
- Sales order processing
- Revenue forecasting

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
